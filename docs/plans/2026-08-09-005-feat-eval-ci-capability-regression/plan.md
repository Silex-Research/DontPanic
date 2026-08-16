---
id: 2026-08-09-005-feat-eval-ci-capability-regression
title: Eval suites in CI — regression gates merges, capability climbs separately
type: feat
tier: cross-cutting
status: ready_for_audit
date: "2026-08-09"
description: >
  Splits the corpus into two suites with opposite expectations. The regression
  suite should pass at essentially 100% and blocks a merge when it does not.
  The capability suite is allowed to fail — a low pass rate there is the point,
  because it marks the hill still to climb — and never blocks anything. Adds
  promotion from capability to regression once a scenario has been stably
  passing, and reports drift rather than only a pass or fail.
motivation: >
  One suite cannot serve both purposes. A gate that includes aspirational tasks
  gets disabled the first week it blocks a legitimate merge; a hill-climbing set
  that gates merges stops being aspirational within a sprint because the cheapest
  way to green is to lower it. Keeping them apart is what lets the gate stay
  strict and the ambition stay honest. The promotion rule is the load-bearing
  part: without it, capability scenarios never graduate and the regression suite
  never grows past whatever was written on day one.
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
  - 2026-08-09-004-feat-agent-graders-task-corpus
  - 2026-05-19-002-feat-install-ux-hardening-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Eval suites in CI

## Target

```yaml
target_env: dev
target_project: none
```

- **repo:** `DontPanic` only.
- **env:** local and CI. The gating suite must run offline with no paid call —
  a merge gate that depends on a model's mood is a merge gate that gets removed.
- **command:** `pytest`, `dontpanic smoke`, the CI workflow for behavioral
  evidence.

## Problem / Motivation

Once the corpus exists, the question is what it is allowed to block. Answering
"everything" and answering "nothing" both fail, in opposite directions and on
different timescales.

- A single suite that gates merges and also contains hard aspirational tasks
  will block a correct change. The pressure at that moment is to weaken the
  task, not to fix the system, and the weakening is invisible afterward.
- A single suite that never gates catches nothing. Regressions land, and the
  eval report becomes a dashboard nobody reads.

So: two suites, opposite expectations, one promotion rule between them, and a
report that distinguishes a regression from a scenario that was always failing.

The promotion rule is where this either works or quietly dies. If graduation
from capability to regression is a matter of taste, nothing graduates, because
nobody wants to be the person who promoted the scenario that later blocked a
release. Making it mechanical — stably passing over N consecutive runs, then
promoted with a recorded decision — removes the judgment call from the moment
where it is hardest to make.

## Proposed Approach

1. **Suite membership (F001).** A scenario declares its suite. Membership lives
   with the scenario, so moving a scenario between suites is a reviewable diff.
2. **Regression runner and gate (F002).** Runs the regression suite offline,
   fails non-zero on any failure, and names the failing scenarios.
3. **Capability runner (F003).** Runs the aspirational suite, reports the pass
   rate, and always exits zero. A capability failure is information.
4. **Promotion (F004).** A capability scenario passing across N consecutive
   recorded runs becomes eligible; promotion writes a decision entry naming the
   runs that justified it.
5. **Drift reporting (F005).** Compare against the previous recorded run so the
   report distinguishes newly-failing from long-failing, and flags a scenario
   whose cost or duration moved sharply even while still passing.
6. **CI wiring (F006).** Regression blocks; capability runs and reports without
   blocking.

## Scope (in)

- Suite membership declared per scenario, with validation.
- Two runners with deliberately different exit-code contracts.
- Mechanical promotion with a recorded justification.
- Drift report distinguishing new failures from standing ones, including cost.
- CI jobs wiring both, only one of which can fail a build.

## Scope (out)

- **Online production sampling and alerting.** Offline suites only. Sampling
  live traffic is a later plan and carries privacy questions this one does not.
- **Changing any system behavior a suite measures.** Same rule as `-004`: a red
  result is a finding, not a licence to move the target.
- **Auto-demotion from regression back to capability.** A regression scenario
  that starts failing is a defect to investigate, not a scenario to reclassify.
  Making demotion easy would make the gate meaningless. Manual only, with a
  recorded reason.
- **Judge-scored dimensions in the gating suite.** D003 keeps the merge gate
  deterministic and offline.

## Acceptance

1. A scenario's suite membership is declared in its own file and validated on
   load; a scenario with no declared suite is rejected rather than defaulted.
2. The regression runner exits non-zero when any regression scenario fails and
   names each failure.
3. The capability runner exits zero even when most of its scenarios fail, and
   reports the pass rate with the raw counts.
4. A capability scenario passing across the configured number of consecutive
   recorded runs is reported as promotion-eligible, and promoting it writes a
   decision entry naming those runs.
5. The drift report distinguishes a scenario that newly failed from one that has
   been failing, and flags a sharp cost or duration move on a still-passing
   scenario.
6. In CI, a regression failure fails the build and a capability failure does not,
   demonstrated by a run of each.
7. No gating run performs a model call, asserted rather than assumed.

## Risks

- **The gate gets disabled.** The standard fate of a slow or flaky merge gate.
  Mitigated by keeping the gating suite offline, deterministic, and small, and
  by reporting its own duration so creep is visible before it becomes intolerable.
- **Promotion never happens.** The likelier failure than bad promotion. D004
  makes eligibility mechanical so the decision is about whether to object, not
  whether to volunteer.
- **Drift comparison against a corrupted baseline.** A bad recorded run silently
  becomes the reference. D005 keeps run records immutable and content-addressed.
- **Two suites become one by neglect.** If capability results are never read,
  the split is administrative. F005's report puts both in one place so the
  aspirational set stays visible next to the gate.
