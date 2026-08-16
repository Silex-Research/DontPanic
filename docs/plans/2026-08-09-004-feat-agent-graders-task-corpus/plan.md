---
id: 2026-08-09-004-feat-agent-graders-task-corpus
title: Graders and a task corpus built from failures that actually happened
type: feat
tier: cross-cutting
status: ready_for_audit
date: "2026-08-09"
description: >
  A harness that can run a scenario twenty times still needs something to judge
  the result. This plan adds three grader families over the artifacts DontPanic
  already writes — deterministic checks on plan artifacts, gates and contracts;
  an operational-validity check that a rendered command is not merely
  well-formed but actually accepted by its target; and a calibrated judge for
  narrative decision quality — and seeds the corpus from recorded failures
  rather than invented happy paths.
motivation: >
  The corpus is the part that cannot be faked. Scenarios written alongside the
  grader that scores them will pass, and prove nothing. DontPanic has a better
  source: a documented history of refusals and misfires, several from a single
  2026-08-09 session, each with a known trigger and a known correct behavior.
  A gate refusing a plan whose acceptance criteria were one run-on sentence; a
  rendered `plan close` that passed token validation and would have failed at
  runtime; an approval that cleared a gate and left the feature unflipped; a
  verdict parser that read four signed-off audits as needing changes because the
  subject's own vocabulary contained the word. Those are labeled cases with
  ground truth, which is exactly what a corpus is and exactly what synthetic
  tasks are not.
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
  - 2026-08-09-003-feat-sim-harness-multi-trial
  - 2026-05-01-004-feat-patch-completeness-gate
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Graders and a task corpus

## Target

```yaml
target_env: dev
target_project: none
```

- **repo:** `DontPanic` only.
- **env:** local only. Deterministic graders must run offline. The judge grader
  reaches a model and is therefore opt-in and never required by a default run.
- **command:** `pytest`, `dontpanic smoke` for behavioral evidence.

## Problem / Motivation

DontPanic's outputs are unusually gradeable. Most agent systems have to judge
prose; this one produces schema-validated artifacts, a gate-state history with
actors and timestamps, an append-only decision log, feature records that carry
evidence references, and a run fingerprint. Almost all of that is checkable by
code.

Three grader families, matched to what can actually be verified:

**Deterministic.** Does the produced plan validate? Does a feature flipped to
passing carry the evidence the schema demands? Does gate-state agree with the
INBOX record of who cleared what? Did the run write outside the repositories its
Target declares? These are facts, and a judge should never be asked to opine on
a fact.

**Operational validity.** This one comes from a failure worth stating plainly.
A rendered `dontpanic plan close` command passed `validate_command_tokens`
cleanly and would have raised at runtime, because `close_plan` refuses any
status other than active. Token-shape validity is not operational validity. A
grader that only checks the former certifies commands that cannot run.

**Judge.** Narrative quality — is a decision entry's rationale actually a
rationale, or a restatement of the decision? Does an audit summary's prose agree
with its structured verdict? The second has a deterministic detector already;
the first genuinely needs a model, and therefore needs calibration against human
labels before anyone trusts its number.

## Proposed Approach

1. **Grader interface (F001).** One contract: takes a trial record and the
   artifacts that trial produced, returns a typed result with a verdict, a
   reason, and the evidence it looked at. Graders compose; none of them writes.
2. **Artifact-conformance graders (F002).** Schema validity of produced
   artifacts, and evidence discipline on any feature flipped to passing.
3. **Consistency graders (F003).** Gate state agreeing with the recorded event
   log, and no write outside the repositories the plan declares.
4. **Operational-validity grader (F004).** For each rendered command, confirm
   the target actually accepts it in a dry-run — not that it parses.
5. **Judge grader (F005).** Model-scored narrative quality, opt-in, with the
   prompt and rubric stored as artifacts so a score is reproducible against a
   known rubric version.
6. **Judge calibration (F006).** A human-labeled subset and a reported agreement
   rate. An uncalibrated judge produces a number with no denominator.
7. **The corpus (F007).** Scenarios reconstructed from recorded failures, each
   citing its source incident.
8. **Corpus growth loop (F008).** A documented path from a real failure to a
   scenario, so the corpus grows from operations rather than from imagination.

## Scope (in)

- Grader interface and the three families above.
- Judge rubric artifacts and a calibration report with an agreement rate.
- Corpus of scenarios reconstructed from recorded failures, each with provenance.
- A documented promotion path from incident to scenario.

## Scope (out)

- **CI wiring and thresholds.** Which graders gate a merge, and at what pass
  rate, is `2026-08-09-005`. This plan produces scores; it does not decide what
  score is acceptable.
- **Changing any behavior a grader measures.** If a grader shows the supervisor
  doing something wrong, that is a finding for a separate plan. A pass that was
  achieved by moving the target is not a pass.
- **Online production sampling.** Offline corpus only.
- **Synthetic task generation.** D002 forbids it for the seed corpus.

## Acceptance

1. Every grader returns a typed result naming its verdict, its reason, and the
   artifact it inspected; no grader mutates anything it is given.
2. A scenario whose run produces a schema-invalid plan artifact is failed by the
   deterministic grader with the schema pointer in the reason.
3. A scenario producing a token-valid but operationally invalid command is
   failed by the operational grader and passed by a token-only check, with both
   results shown side by side as the evidence that the distinction is real.
4. The judge grader is never invoked by a default run and its absence degrades
   the report honestly rather than silently scoring zero.
5. The calibration report states an agreement rate against human labels and the
   size of the labeled set.
6. Every scenario in the corpus cites the incident it was reconstructed from.

## Risks

- **Graders that encode current behavior as correct.** The largest risk in the
  plan. D005 requires each corpus scenario to state the *intended* behavior in
  its own words, independent of what the system currently does, so a scenario
  can fail against today's implementation and be right to.
- **Judge drift.** A rubric edit silently changes every historical score. D004
  versions the rubric and stamps the version into each judged result.
- **Corpus overfitting.** Six scenarios drawn from one session's failures
  describe that session. D006 caps how much of the corpus may come from any
  single source and requires the ratio to be reported.
- **Grading the harness instead of the system.** If a scenario fails because
  the harness mis-scripted an executor, that is a harness bug wearing a grader's
  clothes. F001's result type carries which component the evidence came from so
  the two stay distinguishable.
