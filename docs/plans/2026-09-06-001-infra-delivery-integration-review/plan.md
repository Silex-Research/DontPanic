---
id: 2026-09-06-001-infra-delivery-integration-review
title: Finish proven delivery integrations and decide the next development slices
type: infra
tier: cross-cutting
status: ready_for_audit
date: "2026-09-06"
description: Review parked operator work and August acceptance evidence, wire bounded existing integrations, and specify demand-gated next steps.
agents_required: [codex, claude]
human_gates: [pre_merge]
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# Delivery integration review

## Outcome
Operators get honest readiness warnings and an evidence-backed list of what can
ship, what needs correction, and what should remain parked. This executes the
five steps authorized by the user on 2026-09-06.

## Target
```yaml
target_env: dev
target_project: none
```

## Scope
1. Review all eight operator commits after PR67 without bulk cherry-picking.
2. Audit the six August plans against acceptance and current test evidence.
3. Wire existing advisory conventions and doctor components; prove the existing
   dispatch-role boundary. Design command execution and capture separately.
4. Reassess demand for remote actions, integrations, and harness setup.
5. Produce the opt-in planner revision design, without restoring abandoned intake.

## Boundaries
No paid agent runs, live cloud capture, deployment, blanket status flips, or
manufactured reviewer signoff. Public-entry tests replace fixture-only completion
claims. New command recording/capture interfaces await the requested design choice.
Planner revision is design-only in this slice. A different-vendor review and
required CI on the eventual PR head remain required before merge.
